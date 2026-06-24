import React from 'react';
import styled from 'styled-components';

import ParticlesBackground from '@app/auth/shared/ParticlesBackground';

const Wrapper = styled.div`
    position: relative;
    width: 100%;
    height: 100vh;
    overflow: hidden;
    background-color: #FFFFFF;
`;

const BackgroundLayer = styled.div`
    position: absolute;
    inset: 0;
    z-index: 1;
`;

const Content = styled.div`
    position: relative;
    z-index: 2;
    height: 100%;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
`;

interface Props {
    children: React.ReactNode;
}

export default function AuthPageContainer({ children }: Props) {
    return (
        <Wrapper>
            <BackgroundLayer>
                <ParticlesBackground />
            </BackgroundLayer>
            <Content>{children}</Content>
        </Wrapper>
    );
}
