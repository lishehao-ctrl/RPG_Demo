import React from "react"
import {Composition} from "remotion"
import {AdmissionsDemoTrailer} from "./AdmissionsDemoTrailer"
import {TinyStoriesTrailer} from "./TinyStoriesTrailer"

export const Root: React.FC = () => (
  <>
    <Composition
      id="TinyStoriesTrailer"
      component={TinyStoriesTrailer}
      durationInFrames={1530}
      fps={30}
      width={1920}
      height={1080}
    />
    <Composition
      id="AdmissionsDemoTrailer"
      component={AdmissionsDemoTrailer}
      durationInFrames={2700}
      fps={30}
      width={1920}
      height={1080}
    />
  </>
)
